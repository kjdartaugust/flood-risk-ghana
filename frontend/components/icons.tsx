// Small line icons, drawn here rather than pulled from a package: a handful of
// paths isn't worth a dependency, and these inherit the text colour.
import type { ReactNode } from "react";

function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const SearchIcon = () => (
  <Icon>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
);

export const PinIcon = () => (
  <Icon>
    <path d="M12 21s-7-6.1-7-11.5a7 7 0 0 1 14 0C19 14.9 12 21 12 21z" />
    <circle cx="12" cy="9.5" r="2.5" />
  </Icon>
);

export const LocateIcon = ({ size = 18 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    <circle cx="12" cy="12" r="6" />
    <circle cx="12" cy="12" r="1.5" />
  </Icon>
);

export const ShareIcon = () => (
  <Icon>
    <path d="M12 3v12" />
    <path d="m7 8 5-5 5 5" />
    <path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" />
  </Icon>
);

export const BellIcon = ({ size = 18 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
  </Icon>
);

export const ChevronIcon = () => (
  <Icon size={18}>
    <path d="m9 18 6-6-6-6" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon size={18}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icon>
);

/** A water drop on the brand colour: the FloodWatch mark. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--brand)" />
      <path
        d="M16 6.5c-3.3 4.6-6.6 8-6.6 11.6a6.6 6.6 0 0 0 13.2 0C22.6 14.5 19.3 11.1 16 6.5z"
        fill="#fff"
      />
      <path
        d="M12.6 18.4c.6 1.7 2.2 2.7 4 2.6"
        stroke="var(--brand)"
        strokeWidth="1.7"
        strokeLinecap="round"
        fill="none"
        opacity=".55"
      />
    </svg>
  );
}
