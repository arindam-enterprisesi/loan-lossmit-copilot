import { AssetsScreen } from "@/components/assets/assets-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <AssetsScreen params={params} />;
}
