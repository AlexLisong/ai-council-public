# Acknowledgments and third-party notices

AI Council is inspired by [LLM Council](https://github.com/karpathy/llm-council)
by Andrej Karpathy: asking multiple models to examine a question and bring their
perspectives together. Thank you for sharing that idea and experiment.

This project began as an adaptation of LLM Council. The application implementation
has since been replaced with AI Council's own debate protocol, persistence,
authentication, panels, chat, browser client, and interface. This source release
does not include the earlier fork history. It is not affiliated with or endorsed
by Andrej Karpathy.

AI Council's source is available under the [MIT License](LICENSE). This license
does not grant rights to code in Karpathy's repository. Dependencies and other
third-party material retain their respective licenses.

## Framework scaffolding

The frontend includes scaffolding originating from Vite's React template, including
build, lint, and browser bootstrap conventions. Vite is MIT licensed; its copyright
and permission notice are preserved in [Vite's license](licenses/Vite-MIT.txt).

## Fonts

DM Sans and Instrument Serif are bundled through Fontsource. Both fonts use the
SIL Open Font License 1.1. Their unmodified notices are included in the browser's
public files so production builds carry them alongside the fonts:

- [DM Sans license](frontend/public/licenses/DM-Sans-OFL.txt)
- [Instrument Serif license](frontend/public/licenses/Instrument-Serif-OFL.txt)

## Packages

Python and npm dependencies are installed from the locked manifests. Consult each
package's license before redistributing it; this project's MIT license does not
replace dependency notices. The original vector avatars in `frontend/public/avatars/`
are part of AI Council and covered by its MIT license. Uploaded user content is not
included in this source release.
