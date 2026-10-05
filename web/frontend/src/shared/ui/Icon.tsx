import type { SVGProps } from 'react';

export type IconName =
  | 'archive'
  | 'back'
  | 'board'
  | 'check'
  | 'chevron'
  | 'close'
  | 'download'
  | 'edit'
  | 'history'
  | 'menu'
  | 'palette'
  | 'plus'
  | 'refresh'
  | 'save'
  | 'settings'
  | 'trash'
  | 'user';

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

const paths: Record<IconName, JSX.Element> = {
  archive: <><path d="M4 7h16" /><path d="M5 7l1 13h12l1-13" /><path d="M9 11h6" /><path d="M4 4h16v3H4z" /></>,
  back: <><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></>,
  board: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v10" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m8 10 4 4 4-4" />,
  close: <><path d="m6 6 12 12" /><path d="m18 6-12 12" /></>,
  download: <><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></>,
  edit: <><path d="M4 20h4L19 9l-4-4L4 16v4z" /><path d="m13 7 4 4" /></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l3 2" /></>,
  menu: <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></>,
  palette: <><path d="M12 3a9 9 0 0 0 0 18h1.5a2 2 0 0 0 0-4H12a1.5 1.5 0 0 1 0-3h3a6 6 0 0 0 0-12h-3z" /><path d="M7.5 10h.01M9.5 6.5h.01M14 6h.01M17 9h.01" /></>,
  plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
  refresh: <><path d="M20 7v5h-5" /><path d="M4 17v-5h5" /><path d="M18.5 9A7 7 0 0 0 6 6.5L4 9" /><path d="M5.5 15A7 7 0 0 0 18 17.5l2-2.5" /></>,
  save: <><path d="M5 3h12l3 3v15H4V3h1z" /><path d="M8 3v6h8V3" /><path d="M8 21v-7h8v7" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19 13.5v-3l-2-.7-.7-1.7.9-1.9-2.1-2.1-1.9.9-1.7-.7L10.5 2h-3l-.7 2-1.7.7-1.9-.9-2.1 2.1.9 1.9-.7 1.7L0 10.5v3l2 .7.7 1.7-.9 1.9 2.1 2.1 1.9-.9 1.7.7.7 2.3h3l.7-2 1.7-.7 1.9.9 2.1-2.1-.9-1.9.7-1.7 1.6-.7z" transform="scale(.9) translate(1.3 1.3)" /></>,
  trash: <><path d="M4 7h16" /><path d="M9 7V4h6v3" /><path d="m6 7 1 14h10l1-14" /><path d="M10 11v6M14 11v6" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
};

export function Icon({ name, size = 18, ...props }: IconProps) {
  return (
    <svg
      {...props}
      aria-hidden="true"
      className={`icon ${props.className || ''}`.trim()}
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {paths[name]}
    </svg>
  );
}
