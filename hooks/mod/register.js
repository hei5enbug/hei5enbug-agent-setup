import { registerAgentGuard, registerRolePinning } from "./agents.js";
import { registerWorkBoard } from "./board.js";
import { registerGpt } from "./gpt.js";
import { registerRiskHighlight } from "./risk.js";

const OFF_VALUES = new Set(["false", "0", "off", "no"]);

export function enabled(value) {
  if (value === undefined || value === null || value === true) return true;
  if (value === false || value === 0) return false;
  return !OFF_VALUES.has(String(value).trim().toLowerCase());
}

export function register(on, options) {
  const settings = options ?? {};
  if (enabled(settings.agent_guard)) registerAgentGuard(on);
  if (enabled(settings.role_pinning)) registerRolePinning(on, settings);
  registerGpt(on);
  if (enabled(settings.risk_highlight)) registerRiskHighlight(on);
  if (enabled(settings.work_board)) registerWorkBoard(on);
}
