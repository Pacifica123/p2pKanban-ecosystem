import type { ButtonHTMLAttributes, PropsWithChildren } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, PropsWithChildren {
  variant?: 'default' | 'primary' | 'ghost' | 'danger';
  iconOnly?: boolean;
}

export function Button({ variant = 'default', iconOnly = false, className = '', children, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={`button button--${variant}${iconOnly ? ' button--icon-only' : ''} ${className}`.trim()}
    >
      {children}
    </button>
  );
}
