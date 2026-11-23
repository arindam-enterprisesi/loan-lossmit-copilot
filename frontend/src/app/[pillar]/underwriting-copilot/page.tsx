import { UnderwritingCopilotScreen } from "@/components/copilot/underwriting-copilot-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <UnderwritingCopilotScreen params={params} />;
}
