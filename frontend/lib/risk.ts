// Turning a risk score into plain words: a headline, a reason, and what it
// means for someone about to buy, build or rent. No jargon reaches the page
// from here — the numbers stay available, under "Technical details".
import type { Band, RiskPoint } from "./api";

/** Shared by the map, the verdict and the legend. Low risk is calm green; the
 * ramp warms through amber and red to purple for the worst places. */
export const RISK_COLOR: Record<Band, string> = {
  none: "#8a94a6",
  low: "#2f9e44",
  moderate: "#e0a400",
  high: "#f76707",
  severe: "#e03131",
  extreme: "#9c36b5",
};

export const HEADLINE: Record<Band, string> = {
  none: "Open water",
  low: "Low flood risk",
  moderate: "Some flood risk",
  high: "High flood risk",
  severe: "Very high flood risk",
  extreme: "Extreme flood risk",
};

/**
 * Why this place scores as it does, as a sentence.
 *
 * Only drivers the fitted model actually leans on are offered as reasons
 * (docs/DATA.md, "What the model learned"): low ground counts most, built-up
 * land some, and past floods are a fact worth knowing. Slope points the wrong
 * way in the data and drainage barely counts at this resolution, so neither is
 * ever given as the reason a place floods.
 */
export function reason(r: RiskPoint): string {
  if (r.band === "none") return "This is sea or lagoon, so a flood score doesn't apply.";
  const c = r.components;
  const why: string[] = [];
  if (c.elevation >= 0.6) why.push("it sits low for Accra");
  if (c.historical_flood_density >= 0.35) why.push("floods have been reported nearby");
  if (c.imperviousness >= 0.6 && r.risk_score >= 30) {
    why.push("it's so built-up that rain runs off instead of soaking in");
  }
  if (why.length === 0) {
    return r.band === "low"
      ? "Higher ground than most of Accra, away from known flood spots."
      : "No single cause stands out — it's the mix of terrain and buildings.";
  }
  const last = why[why.length - 1];
  const text =
    why.length === 1
      ? last
      : why.length === 2
        ? `${why[0]} and ${last}`
        : `${why.slice(0, -1).join(", ")}, and ${last}`;
  return text.charAt(0).toUpperCase() + text.slice(1) + ".";
}

export type Plan = "buying" | "building" | "renting";

export const PLAN_LABEL: Record<Plan, string> = {
  buying: "Buying land",
  building: "Building",
  renting: "Renting",
};

const ADVICE: Record<Exclude<Band, "none">, Record<Plan, string>> = {
  low: {
    buying: "Fine for most uses. Check the plot isn't in a gutter path.",
    building: "Standard drainage is enough. Keep gutters and drains clear.",
    renting: "Little to worry about. Ask neighbours how the street copes in heavy rain.",
  },
  moderate: {
    buying: "Ask people nearby about past flooding before you commit.",
    building: "Raise the floor slab a little and plan proper drainage.",
    renting: "Keep valuables off the floor in the rainy season.",
  },
  high: {
    buying: "Get a site survey and ask how high water came in past floods.",
    building: "Build raised, stay clear of drain paths, and budget for drainage.",
    renting: "Avoid ground-floor rooms if you can.",
  },
  severe: {
    buying: "Think twice. Protecting a place like this costs real money.",
    building: "Needs serious flood engineering: raised foundations and proper drains.",
    renting: "Prefer an upper floor, and know your way out in heavy rain.",
  },
  extreme: {
    buying: "Strongly reconsider. This behaves like a flood plain.",
    building: "Not advisable without major flood defences.",
    renting: "Avoid if you can, especially ground floors.",
  },
};

export function advice(band: Band, plan: Plan): string | null {
  return band === "none" ? null : ADVICE[band][plan];
}

/** How much to trust the score, in words a person would use. */
export function sureness(confidence: number): string {
  if (confidence >= 0.75) return "Fairly sure";
  if (confidence >= 0.55) return "Moderately sure";
  return "A rough estimate";
}
