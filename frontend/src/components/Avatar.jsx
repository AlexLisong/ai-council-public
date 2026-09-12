import './Avatar.css';
import { resolveAvatar } from '../avatars';

export default function Avatar({ member, index = 0, chairman = false, size = 40, className = '', decorative = true }) {
  const avatar = resolveAvatar(member, index, chairman);
  const src = avatar.startsWith('data:') ? avatar : `/avatars/${avatar}.svg`;
  return <img className={`seat-avatar ${className}`} src={src} width={size} height={size}
    style={{ '--avatar-size': `${size}px` }} alt={decorative ? '' : `${member?.name || (chairman ? 'Chairman' : 'AI member')} profile`}
    draggable="false" />;
}
