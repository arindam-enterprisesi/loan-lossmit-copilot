import { SettingsScreen } from "@/components/settings/settings-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <SettingsScreen params={params} />;
}
