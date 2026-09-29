const KANA: Record<string, string> = {
  あ: "a", い: "i", う: "u", え: "e", お: "o",
  か: "ka", き: "ki", く: "ku", け: "ke", こ: "ko",
  が: "ga", ぎ: "gi", ぐ: "gu", げ: "ge", ご: "go",
  さ: "sa", し: "shi", す: "su", せ: "se", そ: "so",
  ざ: "za", じ: "ji", ず: "zu", ぜ: "ze", ぞ: "zo",
  た: "ta", ち: "chi", つ: "tsu", て: "te", と: "to",
  だ: "da", ぢ: "ji", づ: "zu", で: "de", ど: "do",
  な: "na", に: "ni", ぬ: "nu", ね: "ne", の: "no",
  は: "ha", ひ: "hi", ふ: "fu", へ: "he", ほ: "ho",
  ば: "ba", び: "bi", ぶ: "bu", べ: "be", ぼ: "bo",
  ぱ: "pa", ぴ: "pi", ぷ: "pu", ぺ: "pe", ぽ: "po",
  ま: "ma", み: "mi", む: "mu", め: "me", も: "mo",
  や: "ya", ゆ: "yu", よ: "yo",
  ら: "ra", り: "ri", る: "ru", れ: "re", ろ: "ro",
  わ: "wa", ゐ: "i", ゑ: "e", を: "o", ん: "n", ゔ: "vu",
  ぁ: "a", ぃ: "i", ぅ: "u", ぇ: "e", ぉ: "o",
  ゃ: "ya", ゅ: "yu", ょ: "yo", ゎ: "wa",
};

const DIGRAPHS: Record<string, string> = {
  きゃ: "kya", きゅ: "kyu", きょ: "kyo",
  ぎゃ: "gya", ぎゅ: "gyu", ぎょ: "gyo",
  しゃ: "sha", しゅ: "shu", しょ: "sho",
  じゃ: "ja", じゅ: "ju", じょ: "jo",
  ちゃ: "cha", ちゅ: "chu", ちょ: "cho",
  ぢゃ: "ja", ぢゅ: "ju", ぢょ: "jo",
  にゃ: "nya", にゅ: "nyu", にょ: "nyo",
  ひゃ: "hya", ひゅ: "hyu", ひょ: "hyo",
  びゃ: "bya", びゅ: "byu", びょ: "byo",
  ぴゃ: "pya", ぴゅ: "pyu", ぴょ: "pyo",
  みゃ: "mya", みゅ: "myu", みょ: "myo",
  りゃ: "rya", りゅ: "ryu", りょ: "ryo",
  うぃ: "wi", うぇ: "we", うぉ: "wo",
  ゔぁ: "va", ゔぃ: "vi", ゔぇ: "ve", ゔぉ: "vo",
  ふぁ: "fa", ふぃ: "fi", ふぇ: "fe", ふぉ: "fo",
  てぃ: "ti", でぃ: "di", とぅ: "tu", どぅ: "du",
  しぇ: "she", じぇ: "je", ちぇ: "che",
  つぁ: "tsa", つぃ: "tsi", つぇ: "tse", つぉ: "tso",
  くぁ: "kwa", ぐぁ: "gwa",
};

const PARTICLES: Record<string, string> = { は: "wa", へ: "e", を: "o" };

function hiragana(value: string): string {
  return value.normalize("NFKC").replace(/[\u30a1-\u30f6]/gu, (character) =>
    String.fromCharCode(character.charCodeAt(0) - 0x60),
  );
}

function baseRomaji(mora: string): string {
  const normalized = hiragana(mora);
  if (DIGRAPHS[normalized]) return DIGRAPHS[normalized];
  if (normalized.endsWith("ー")) {
    return `${baseRomaji(normalized.slice(0, -1))}-`;
  }
  if (normalized === "ー") return "-";
  return [...normalized].map((character) => KANA[character] ?? character).join("");
}

function geminatePrefix(next: string): string {
  if (next.startsWith("ch")) return "c";
  const first = next[0] ?? "";
  return /[aeioun]/u.test(first) ? "" : first;
}

/** Convert timing-sized kana chunks to the SUG/Kirakara display spelling. */
export function romanizeReadingMoras(
  moras: string[],
  surface?: string,
): string[] {
  const normalizedSurface = surface ? hiragana(surface) : undefined;
  return moras.map((mora, index) => {
    const normalized = hiragana(mora);
    if (
      normalizedSurface &&
      moras.length === 1 &&
      normalizedSurface.length === 1 &&
      normalizedSurface === normalized &&
      PARTICLES[normalized]
    ) {
      return PARTICLES[normalized];
    }
    if (normalized === "っ") {
      const next = baseRomaji(moras[index + 1] ?? "");
      return geminatePrefix(next) || "xtsu";
    }
    if (normalized === "ん") {
      const next = baseRomaji(moras[index + 1] ?? "");
      return /^[aeiouy]/u.test(next) ? "n'" : "n";
    }
    if (normalized.endsWith("っ") && normalized.length > 1) {
      const next = baseRomaji(moras[index + 1] ?? "");
      return `${baseRomaji(normalized.slice(0, -1))}${geminatePrefix(next)}`;
    }
    return baseRomaji(normalized);
  });
}
