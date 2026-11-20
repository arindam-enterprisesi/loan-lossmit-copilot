import { HardshipScreen } from "@/components/hardship/hardship-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <HardshipScreen params={params} />;
}
