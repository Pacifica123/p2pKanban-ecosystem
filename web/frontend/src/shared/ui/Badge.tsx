import type { PropsWithChildren } from 'react';

interface BadgeProps extends PropsWithChildren {
  tone?: string;
}

export function Badge({ tone = 'default', children }: BadgeProps) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
