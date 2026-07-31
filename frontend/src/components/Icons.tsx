/** Inline stroke icons, so the app keeps its zero-dependency icon story. */
type Props = { className?: string };

const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  viewBox: '0 0 24 24',
};

export const PlusIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><path d="M12 5v14M5 12h14" /></svg>
);

export const MenuIcon = ({ className = 'h-5 w-5' }: Props) => (
  <svg {...base} className={className}><path d="M4 6h16M4 12h16M4 18h16" /></svg>
);

export const CloseIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><path d="M6 6l12 12M18 6L6 18" /></svg>
);

export const TrashIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" />
  </svg>
);

export const PencilIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M16.5 4.5a2.1 2.1 0 013 3L8 19l-4 1 1-4z" />
  </svg>
);

export const CopyIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 012-2h9" />
  </svg>
);

export const CheckIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><path d="M4.5 12.5l5 5 10-11" /></svg>
);

export const RetryIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M20 12a8 8 0 11-2.6-5.9M20 4v4h-4" />
  </svg>
);

export const StopIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><rect x="7" y="7" width="10" height="10" rx="2" /></svg>
);

export const SendIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><path d="M5 12l14-7-5.5 14L11 13z" /></svg>
);

export const DownloadIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 4v10m0 0l-4-4m4 4l4-4M5 18h14" />
  </svg>
);

export const ChevronDownIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}><path d="M6 9l6 6 6-6" /></svg>
);

export const SparkIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
  </svg>
);

export const SidebarIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </svg>
);

export const LogoutIcon = ({ className = 'h-4 w-4' }: Props) => (
  <svg {...base} className={className}>
    <path d="M15 17l5-5-5-5M20 12H9M11 4H6a2 2 0 00-2 2v12a2 2 0 002 2h5" />
  </svg>
);
