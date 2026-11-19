export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = {
  variant?: ButtonVariant;
  type?: "button" | "submit";
  children?: unknown;
};

export function Button({ variant = "primary", type = "button", children }: ButtonProps) {
  return (
    <button type={type} className={`btn btn-${variant}`}>
      {children}
    </button>
  );
}
