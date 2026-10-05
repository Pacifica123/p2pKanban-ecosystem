import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

interface BaseFieldProps {
  label: string;
}

export function TextField({ label, ...props }: BaseFieldProps & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <input className="field__input" {...props} />
    </label>
  );
}

export function TextAreaField({ label, ...props }: BaseFieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <textarea className="field__textarea" {...props} />
    </label>
  );
}

export function SelectField({ label, children, ...props }: BaseFieldProps & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <select className="field__select" {...props}>
        {children}
      </select>
    </label>
  );
}
