import { HitlScreen } from "@/components/hitl/hitl-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <HitlScreen params={params} />;
}
