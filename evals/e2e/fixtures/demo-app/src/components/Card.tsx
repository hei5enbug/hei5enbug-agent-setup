type CardProps = {
  title: string;
  testId?: string;
  children?: unknown;
};

export function Card({ title, testId, children }: CardProps) {
  return (
    <section className="card" data-testid={testId}>
      <h2 className="card-title">{title}</h2>
      {children}
    </section>
  );
}
