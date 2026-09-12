"""FastAPI backend for AI Council."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import auth, db
from . import panels, throttle
from .chat import TITLE_WAIT_SECONDS, fallback_title, prepare_chat_history, resolve_chat_config
from .config import ALLOW_SIGNUP, HOST, PORT, ROOT_DIR, public_config
from .debate import generate_title, parse_quorum, resolve_debate_config, run_debate
from .discussion import HistoryLimitError, prepare_discussion, previous_settings
from .interaction import ActiveRuns, RunController, RunStreamingResponse
from .providers import ChatError, close_client, stream_chat
from .streaming import with_heartbeats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("council")
active_runs = ActiveRuns()


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.bootstrap_admin()
    db.migrate_retired_models()
    db.recover_interrupted_runs()
    yield
    await close_client()


app = FastAPI(title="AI Council API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- schemas -----------------------------------------------------------------

class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20000)
    provider: Optional[str] = Field(default=None, min_length=1, max_length=80)
    model: Optional[str] = Field(default=None, min_length=1, max_length=200)
    preset: Optional[str] = Field(default=None, max_length=100)
    max_rounds: Optional[int] = Field(default=None, ge=0, le=10, strict=True)
    consensus: Optional[str] = Field(default=None, max_length=20)
    pause_for_input: Optional[bool] = Field(default=None, strict=True)
    use_latest_panel: bool = Field(default=False, strict=True)

    @field_validator("content", "preset", "provider", "model")
    @classmethod
    def _not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _model_pair(self):
        if (self.provider is None) != (self.model is None):
            raise ValueError("Choose both a provider and a model")
        return self

    @field_validator("consensus")
    @classmethod
    def _consensus_parses(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            parse_quorum(v, 4)
        except (ValueError, ZeroDivisionError) as e:
            raise ValueError(f"consensus must be 'all', 'majority', a fraction like '2/3', or a number 0-1: {e}")
        return v


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["chat", "council"] = "council"


class HumanInputRequest(BaseModel):
    content: Optional[str] = Field(default=None, max_length=20000)
    skip: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def _one_action(self):
        self.content = self.content.strip() if self.content is not None else None
        if self.skip and self.content:
            raise ValueError("Send a thought or skip, not both")
        if not self.skip and not self.content:
            raise ValueError("Enter a thought or set skip to true")
        return self


# ---- helpers -----------------------------------------------------------------

def _load_for(user: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    """Load a conversation the user may access, or 404 (never reveal that it exists)."""
    conversation = db.get_conversation(conversation_id) if conversation_id.replace("-", "").isalnum() else None
    if conversation is None or not auth.can_access(user, conversation):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---- public ------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AI Council API"}


@app.get("/api/auth/settings")
async def auth_settings():
    return {"allow_signup": ALLOW_SIGNUP}


@app.post("/api/auth/register")
async def register(creds: Credentials):
    if not ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="Sign-up is disabled on this server")
    throttle.check_registration()
    username = auth.validate_username(creds.username)
    auth.validate_password(creds.password)
    if db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="That username is taken")
    user = db.create_user(username, auth.hash_password(creds.password))
    return {"token": auth.issue_token(user["id"]), "user": auth.public_user(user)}


@app.post("/api/auth/login")
async def login(creds: Credentials):
    throttle.check_login(creds.username)
    user = db.get_user_by_username(creds.username.strip())
    if user is None or not auth.verify_password(creds.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    return {"token": auth.issue_token(user["id"]), "user": auth.public_user(user)}


# ---- signed in ---------------------------------------------------------------

@app.get("/api/auth/me")
async def me(user: dict[str, Any] = Depends(auth.current_user)):
    return auth.public_user(user)


@app.post("/api/auth/logout", status_code=204)
async def logout(request: Request, user: dict[str, Any] = Depends(auth.current_user)):
    auth.revoke_token(request.state.token)


@app.get("/api/config")
async def get_config(user: dict[str, Any] = Depends(auth.current_user)):
    try:
        config = public_config()
        config["presets"].extend(panels.public_panel(panel) for panel in db.list_panels(user["id"]))
        return config
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e))


def _saved_definition(request: panels.PanelRequest) -> dict[str, Any]:
    """The editor is the authority on models: drop remap provenance when a user saves."""
    definition = request.model_dump()
    for member in [*definition["seats"], definition["chairman"]]:
        member.pop("replaced_model", None)
    return definition


@app.post("/api/panels", status_code=201)
async def create_panel(request: panels.PanelRequest, user: dict[str, Any] = Depends(auth.current_user)):
    definition = _saved_definition(request)
    try:
        panels.validate_models(definition)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return panels.public_panel(db.create_panel(str(uuid.uuid4()), user["id"], definition))


@app.put("/api/panels/{panel_id}")
async def update_panel(panel_id: str, request: panels.PanelRequest, user: dict[str, Any] = Depends(auth.current_user)):
    owned = panels.owned_panel(panel_id, user["id"])
    definition = _saved_definition(request)
    try:
        panels.validate_models(definition)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    updated = db.update_panel(owned["id"], user["id"], definition)
    if updated is None:
        raise HTTPException(status_code=404, detail="Panel not found")
    return panels.public_panel(updated)


@app.get("/api/panels/{panel_id}")
async def get_panel(panel_id: str, user: dict[str, Any] = Depends(auth.current_user)):
    return panels.public_panel(panels.owned_panel(panel_id, user["id"]))


@app.get("/api/conversations")
async def list_conversations(scope: str = "mine", user: dict[str, Any] = Depends(auth.current_user)):
    """Own conversations by default; `scope=all` lists everyone's and is admin-only."""
    if scope == "all":
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Master account required")
        return db.list_conversations(None)
    return db.list_conversations(user["id"])


@app.post("/api/conversations")
async def create_conversation(request: CreateConversationRequest | None = None, user: dict[str, Any] = Depends(auth.current_user)):
    return db.create_conversation(str(uuid.uuid4()), user["id"], mode=request.mode if request else "council")


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict[str, Any] = Depends(auth.current_user)):
    conversation = _load_for(user, conversation_id)
    conversation["is_running"] = active_runs.get(conversation_id) is not None
    messages = conversation["messages"]
    if not conversation["is_running"] and messages and db.mark_interrupted_assistant(messages[-1]):
        db.save_messages(conversation_id, messages)
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user: dict[str, Any] = Depends(auth.current_user)):
    conversation = _load_for(user, conversation_id)
    if conversation["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can delete this conversation")
    if active_runs.get(conversation_id) is not None:
        raise HTTPException(status_code=409, detail="Wait for the current response to finish before deleting this conversation.")
    db.delete_conversation(conversation_id)


@app.get("/api/admin/users")
async def admin_users(_: dict[str, Any] = Depends(auth.current_admin)):
    return db.list_users()


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    user: dict[str, Any] = Depends(auth.current_user),
):
    """Run the saved conversation's mode. Owners alone may append and generate."""
    conversation = _load_for(user, conversation_id)
    if conversation["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can send messages in this conversation")
    if conversation["mode"] == "chat":
        return _chat_stream_response(conversation, request)
    if request.provider is not None:
        raise HTTPException(status_code=422, detail="Council models are selected through the panel settings")
    messages: list[dict[str, Any]] = conversation["messages"]
    is_first_message = len(messages) == 0
    prior = previous_settings(messages)
    try:
        discussion = prepare_discussion(messages, request.content)
        preset_key, selected_panel = panels.select_panel(user["id"], request.preset, prior, request.use_latest_panel)
        config = resolve_debate_config(
            preset_key,
            request.max_rounds if request.max_rounds is not None else prior.get("max_rounds"),
            request.consensus if request.consensus is not None else prior.get("consensus"),
            request.pause_for_input if request.pause_for_input is not None else prior.get("pause_for_input", True),
            resolved_panel=selected_panel,
        )
    except HistoryLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    config.update({"mode": "council", "turn_number": discussion.turn_number, "is_followup": discussion.turn_number > 1})
    assistant: dict[str, Any] = {
        "role": "assistant", "mode": "council", "config": config, "rounds": [], "final": None, "error": None,
        "human_inputs": discussion.human_inputs, "waiting_for_input": None,
    }
    controller = RunController(assistant, discussion, lambda: db.save_messages(conversation_id, messages))
    lease = active_runs.acquire(conversation_id, controller)

    async def event_generator():
        title_task: Optional[asyncio.Task] = None
        started = False
        try:
            messages.append({"role": "user", "content": request.content})
            messages.append(assistant)
            db.save_messages(conversation_id, messages)
            started = True
            if is_first_message:
                title_task = asyncio.create_task(generate_title(discussion.original_question, chairman=config["chairman"]))

            async with aclosing(run_debate(
                discussion.original_question, discussion=discussion, config=config,
                pause_after=controller.pause_after if config["pause_for_input"] else None,
            )) as debate:
                async for event in debate:
                    if event["type"] == "config":
                        assistant["config"] = event["data"]
                    elif event["type"] == "round_complete":
                        assistant["rounds"].append(event["data"])
                        db.save_messages(conversation_id, messages)
                    elif event["type"] == "final_complete":
                        assistant["final"] = event["data"]
                        db.save_messages(conversation_id, messages)
                    elif event["type"] == "error":
                        assistant["error"] = event["message"]
                    yield _sse(event)
                    if event["type"] == "error":
                        break

            if title_task:
                title = await title_task
                db.update_title(conversation_id, title)
                yield _sse({"type": "title_complete", "data": {"title": title}})

            yield _sse({"type": "complete"})
        except (asyncio.CancelledError, GeneratorExit):
            log.info("client disconnected during debate %s; keeping %d completed round(s)", conversation_id, len(assistant["rounds"]))
            assistant["error"] = assistant["error"] or "Debate interrupted: the client disconnected."
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("debate failed")
            assistant["error"] = str(e)
            yield _sse({"type": "error", "message": str(e)})
        finally:
            try:
                controller.waiting = None
                assistant["waiting_for_input"] = None
                if started:
                    try:
                        db.save_messages(conversation_id, messages)
                    except Exception:  # noqa: BLE001
                        log.exception("could not persist final state of conversation %s", conversation_id)
                if title_task and not title_task.done():
                    title_task.cancel()
                if title_task:
                    await asyncio.gather(title_task, return_exceptions=True)
            finally:
                lease.release()

    return RunStreamingResponse(
        with_heartbeats(event_generator()),
        lease=lease,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _chat_stream_response(conversation: dict[str, Any], request: SendMessageRequest) -> RunStreamingResponse:
    conversation_id = conversation["id"]
    messages = conversation["messages"]
    is_first_message = not messages
    try:
        history, turn_number = prepare_chat_history(messages, request.content)
        config = resolve_chat_config(messages, request.provider, request.model)
    except HistoryLimitError as error:
        raise HTTPException(status_code=413, detail=str(error))
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    config.update({"turn_number": turn_number, "is_followup": turn_number > 1})
    assistant = {
        "role": "assistant", "mode": "chat", "config": config, "content": "",
        "final": None, "error": None, "rounds": [], "human_inputs": [], "waiting_for_input": None,
    }
    controller = RunController(assistant, None, lambda: db.save_messages(conversation_id, messages))
    lease = active_runs.acquire(conversation_id, controller)

    async def events():
        title_task: asyncio.Task | None = None
        started = False
        try:
            messages.extend([{"role": "user", "content": request.content}, assistant])
            db.save_messages(conversation_id, messages)
            started = True
            if is_first_message:
                title_task = asyncio.create_task(generate_title(request.content, chairman=config))
            yield _sse({"type": "config", "data": config})
            last_saved_at, last_saved_length = 0.0, 0
            async with aclosing(stream_chat(config["provider"], config["model"], history)) as deltas:
                async for delta in deltas:
                    assistant["content"] += delta
                    now = asyncio.get_running_loop().time()
                    if now - last_saved_at >= 1 or len(assistant["content"]) - last_saved_length >= 2048:
                        db.save_messages(conversation_id, messages)
                        last_saved_at, last_saved_length = now, len(assistant["content"])
                    yield _sse({"type": "chat_delta", "data": {"content": delta}})
            if not assistant["content"].strip():
                raise ChatError("The model returned an empty response. Please try again.")
            assistant["final"] = {
                "response": assistant["content"], "provider": config["provider"], "model": config["model"],
            }
            db.save_messages(conversation_id, messages)
            yield _sse({"type": "final_complete", "data": assistant["final"]})
            if title_task:
                try:
                    title = await asyncio.wait_for(title_task, timeout=TITLE_WAIT_SECONDS)
                except Exception:  # A slow or failed title must not hold a finished chat open.
                    title = fallback_title(request.content)
                db.update_title(conversation_id, title)
                yield _sse({"type": "title_complete", "data": {"title": title}})
            yield _sse({"type": "complete"})
        except (asyncio.CancelledError, GeneratorExit):
            if assistant["final"] is None:
                assistant["error"] = "Chat interrupted: the client disconnected. Your partial response is saved."
            log.info("client disconnected during chat %s; keeping %d response characters", conversation_id, len(assistant["content"]))
            raise
        except Exception as error:  # noqa: BLE001 - do not expose upstream URLs, credentials, or tracebacks.
            log.exception("chat failed for conversation %s", conversation_id)
            assistant["error"] = str(error) if isinstance(error, ChatError) else "The response could not finish. Please try again."
            yield _sse({"type": "error", "message": assistant["error"]})
            yield _sse({"type": "complete"})
        finally:
            try:
                if started:
                    try:
                        db.save_messages(conversation_id, messages)
                    except Exception:  # noqa: BLE001
                        log.exception("could not persist final state of chat %s", conversation_id)
                if title_task and not title_task.done():
                    title_task.cancel()
                if title_task:
                    await asyncio.gather(title_task, return_exceptions=True)
            finally:
                lease.release()

    return RunStreamingResponse(
        with_heartbeats(events()), lease=lease, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/api/conversations/{conversation_id}/input")
async def submit_human_input(
    conversation_id: str,
    request: HumanInputRequest,
    user: dict[str, Any] = Depends(auth.current_user),
):
    conversation = _load_for(user, conversation_id)
    if conversation["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the owner can contribute to this conversation")
    lease = active_runs.get(conversation_id)
    if lease is None:
        raise HTTPException(status_code=409, detail="The council is not waiting for input. Send a follow-up after the final answer.")
    try:
        return lease.controller.submit(request.content, request.skip)
    except HistoryLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))


class FrontendFiles(StaticFiles):
    @staticmethod
    def is_app_route(path: str) -> bool:
        path = path.rstrip("/")
        if path in {"login", "debates", "panels", "panels/new"}:
            return True
        resource, separator, identifier = path.partition("/")
        if separator and resource in {"debates", "panels"}:
            try:
                return str(uuid.UUID(identifier)) == identifier.lower()
            except ValueError:
                pass
        return False

    async def get_response(self, path: str, scope):
        # The entire /api namespace stays an API even if a build contains a
        # similarly named file; missing endpoints must not return frontend HTML.
        if path == "api" or path.startswith("api/") or any(part.startswith(".") and part != "." for part in path.split("/")):
            raise HTTPException(status_code=404, detail="Not Found")
        if self.is_app_route(path):
            return await super().get_response("index.html", scope)
        return await super().get_response(path, scope)


def mount_frontend(application: FastAPI, directory: Path) -> None:
    """Mount after API routes, retaining the development root health response."""
    if (directory / "index.html").is_file():
        application.mount("/", FrontendFiles(directory=directory, html=True), name="frontend")
    else:
        application.add_api_route("/", health, include_in_schema=False)


mount_frontend(app, ROOT_DIR / "frontend" / "dist")


if __name__ == "__main__":
    import uvicorn

    # Default is loopback. Set HOST=0.0.0.0 only when serving other people over a network you trust or behind TLS.
    uvicorn.run(app, host=HOST, port=PORT)
