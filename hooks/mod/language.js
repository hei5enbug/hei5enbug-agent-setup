const KOREAN = new Set(["korean", "ko", "한국어"]);

export async function responseLanguage($) {
  try {
    const value = (await $.settings.read()).language;
    const text = typeof value === "string" ? value.trim().toLowerCase() : "";
    return KOREAN.has(text) || KOREAN.has(text.split(/[-_]/)[0]) ? "Korean" : "English";
  } catch {
    return "English";
  }
}
