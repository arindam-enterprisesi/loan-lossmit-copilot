import { IncomeScreen } from "@/components/income/income-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <IncomeScreen params={params} />;
}
