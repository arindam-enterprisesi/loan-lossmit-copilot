import {
  Bot,
  Calculator,
  ClipboardCheck,
  FileText,
  FolderOpen,
  Gauge,
  Home,
  Landmark,
  LayoutDashboard,
  MessageSquare,
  Scale,
  Search,
  Settings,
  ShieldCheck,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Pillar } from "./types";

export interface NavItem {
  /** URL segment under /{pillar}/. "" is the dashboard. */
  slug: string;
  label: string;
  icon: LucideIcon;
  /** "live" screens are built; "soon" show a placeholder. Flip as screens land. */
  status: "live" | "soon";
}

export interface PillarConfig {
  key: Pillar;
  /** Product name shown at the top of the left nav (matches the PRD screens). */
  title: string;
  shortTitle: string;
  icon: LucideIcon;
  nav: NavItem[];
}

const shared = {
  businessChat: { slug: "business-chat", label: "Business chat", icon: MessageSquare, status: "soon" },
  hitl: { slug: "hitl-actions", label: "HITL actions", icon: Users, status: "soon" },
  governance: { slug: "agent-governance", label: "Agent governance", icon: ShieldCheck, status: "soon" },
  context: { slug: "context-settings", label: "Context settings", icon: Settings, status: "soon" },
  profile: { slug: "profile", label: "Profile", icon: User, status: "soon" },
} satisfies Record<string, NavItem>;

// Navigation follows the left menu on the PRD mock-ups (Loan Processing PRD slide 12/13,
// Loss Mitigation PRD slide 12/13). "Cases" is added so both demo cases are reachable.
export const PILLARS: Record<Pillar, PillarConfig> = {
  underwriting: {
    key: "underwriting",
    title: "Loan Processing Copilot",
    shortTitle: "Loan Processing",
    icon: Landmark,
    nav: [
      { slug: "", label: "Dashboard", icon: LayoutDashboard, status: "live" },
      { slug: "cases", label: "Cases", icon: FolderOpen, status: "live" },
      shared.businessChat,
      { slug: "document-intelligence", label: "Document intelligence", icon: FileText, status: "soon" },
      { slug: "income-analysis", label: "Income analysis", icon: Calculator, status: "soon" },
      { slug: "assets-liabilities", label: "Assets and liabilities", icon: Scale, status: "soon" },
      { slug: "credit-report", label: "Credit report", icon: Gauge, status: "soon" },
      { slug: "guideline-assistant", label: "Guideline assistant", icon: Search, status: "soon" },
      { slug: "underwriting-copilot", label: "Underwriting copilot", icon: Bot, status: "soon" },
      shared.hitl,
      shared.governance,
      shared.context,
      shared.profile,
    ],
  },
  loss_mitigation: {
    key: "loss_mitigation",
    title: "Loss Mitigation Copilot",
    shortTitle: "Loss Mitigation",
    icon: Home,
    nav: [
      { slug: "", label: "Dashboard", icon: LayoutDashboard, status: "live" },
      { slug: "cases", label: "Cases", icon: FolderOpen, status: "live" },
      shared.businessChat,
      { slug: "document-intake", label: "Document intake", icon: ClipboardCheck, status: "soon" },
      { slug: "hardship-budget", label: "Hardship and budget", icon: Calculator, status: "soon" },
      { slug: "recommendation", label: "Recommendation", icon: Scale, status: "soon" },
      shared.hitl,
      shared.governance,
      { slug: "agent-performance", label: "Agent performance", icon: Gauge, status: "soon" },
      shared.context,
      shared.profile,
    ],
  },
};

/** URL segment used for each pillar. */
export const PILLAR_SLUG: Record<Pillar, string> = {
  underwriting: "underwriting",
  loss_mitigation: "loss-mitigation",
};

export function pillarFromSlug(slug: string): Pillar | null {
  const hit = (Object.keys(PILLAR_SLUG) as Pillar[]).find((p) => PILLAR_SLUG[p] === slug);
  return hit ?? null;
}

export function navHref(pillar: Pillar, slug: string): string {
  return slug ? `/${PILLAR_SLUG[pillar]}/${slug}` : `/${PILLAR_SLUG[pillar]}`;
}

export function findNavItem(pillar: Pillar, slug: string): NavItem | undefined {
  return PILLARS[pillar].nav.find((n) => n.slug === slug);
}
