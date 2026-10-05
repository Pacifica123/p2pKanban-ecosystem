import type { PropsWithChildren, ReactNode } from 'react';

interface PanelProps extends PropsWithChildren {
  title?: string;
  description?: string;
  actions?: ReactNode;
}

export function Panel({ title, description, actions, children }: PanelProps) {
  return (
    <section className="panel">
      {title || actions ? (
        <div className="entity-header">
          <div>
            {title ? <h3>{title}</h3> : null}
            {description ? <p className="muted">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}
