import labels from "../preview/labels.json";

type Table = Record<string, string>;
const tables = labels as unknown as Record<string, Table>;

export const pageLabels: Record<string, string> = {
  "Command Center": "Vue d'ensemble", "AI Agents": "Agents IA", "Skills Library": "Compétences",
  "Market Intelligence": "Actualités et marché", "Trading Terminal": "Journal des signaux",
  "Session Analytics": "Sessions", "Strategy Lab": "Backtests", "AI Memory": "Mémoire collective",
  "Risk Center": "Gestion des risques", "API & Integrations": "Intégrations", "Budget Center": "Budget IA",
  "Settings": "Paramètres"
};

/** One plain-language sentence per page: what it shows and how to read it. */
export const pageHelp: Record<string, string> = {
  "Command Center": "Résumé de l'état du système. Aucun ordre ne peut partir. Le compte démo est lu par des commandes en lecture seule, pas encore par cette interface : les tirets « — » signifient « pas encore affiché ici ».",
  "AI Agents": "Chaque cycle de recherche produit un avis par rôle. « ATTENTE » est la réponse normale : le système préfère ne rien proposer quand les preuves manquent.",
  "Skills Library": "Catalogue de méthodes d'analyse rédigées comme spécifications : 27 prévues au cahier des charges et 7 propres aux indices synthétiques. Ce ne sont pas des stratégies validées.",
  "Market Intelligence": "Titres d'actualité reçus et triés par pertinence pour l'or. Aucun titre n'est une confirmation ni un signal d'achat ou de vente.",
  "Trading Terminal": "Décisions de recherche du système. Aucun ordre n'est envoyé au courtier ; « ATTENTE » signifie qu'aucune entrée n'est proposée.",
  "Session Analytics": "Sessions de marché (Londres, New York…) données à titre indicatif ; elles devront être confirmées avec les horaires du courtier.",
  "Strategy Lab": "Résultats de tests sur données passées. Les exemples sont artificiels et ne mesurent aucun rendement futur.",
  "AI Memory": "Notes automatiques : désaccords entre un modèle et la base déterministe, pannes. Rien n'est modifié automatiquement.",
  "Risk Center": "État des protections. L'arrêt des nouvelles entrées est actif par défaut et le trading réel est interdit.",
  "API & Integrations": "Liste des conditions qu'il reste à remplir avant l'expérience de 14 jours en démo, et état des accès configurés.",
  "Budget Center": "Dépenses des modèles d'IA et plafonds. Quand un plafond est atteint, les nouveaux appels sont bloqués.",
  "Settings": "Modèles d'IA et plafonds de budget, enregistrés côté serveur avec un numéro de version. Une clé opérateur est demandée."
};

export function fr(table: keyof typeof labels, key: unknown, fallback?: string): string {
  if (typeof key !== "string" || key === "") return fallback ?? "—";
  const entry = tables[table as string]?.[key];
  return entry ?? fallback ?? key;
}

export function role(agent: unknown): string { return fr("roles", agent); }
export function action(value: unknown): string { return fr("actions", value); }

export function rationale(text: unknown): string {
  if (typeof text !== "string" || text === "") return "—";
  const known = tables.rationales[text];
  if (known) return known;
  for (const [pattern, replacement] of labels.rationalePatterns as [string, string][]) {
    const match = new RegExp(pattern).exec(text);
    if (match) return replacement.replace(/\$(\d)/g, (_, n) => match[Number(n)] ?? "");
  }
  return text;
}

export function gate(id: string): { label: string; help: string } {
  const entry = (labels.gates as Record<string, string[]>)[id];
  return entry ? { label: entry[0], help: entry[1] } : { label: id, help: "" };
}

export function when(iso: unknown): string {
  if (typeof iso !== "string") return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}
