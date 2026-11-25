import { RecommendationScreen } from "@/components/recommendation/recommendation-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <RecommendationScreen params={params} />;
}
