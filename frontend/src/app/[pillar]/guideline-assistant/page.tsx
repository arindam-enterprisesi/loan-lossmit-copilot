import { GuidelineScreen } from "@/components/guidelines/guideline-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <GuidelineScreen params={params} />;
}
