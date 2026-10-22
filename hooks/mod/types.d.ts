export type RiskMark = { level: "critical" | "always" | "write"; label: string; impact: string | null };
export type BoardAgentTimes = { startedAt: number | null; endedAt: number | null };
export type BoardCache = { read: number; creation: number; input: number };
export type BoardLimit = { kind: string; percentUsed: number; resetsAt: string | null };
export type BoardUsage = { contextPercent: number | null; rateLimits: BoardLimit[] };
export type BoardCodex = { at: number | null; percent: number | null };

declare module "claude-code" {
  interface PluginState {
    "hei5enbug-agent-setup": {
      riskMarks: StateFamily<RiskMark | null>;
      boardEdits: Record<string, string[]>;
      boardAgents: Record<string, BoardAgentTimes>;
      boardAnnounced: string[];
      boardCache: BoardCache;
      boardUsage: BoardUsage | null;
      boardCodex: BoardCodex;
      boardTick: number;
      boardMainActive: boolean;
    };
  }
}
