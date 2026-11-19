import { ReviewScreen } from "@/components/documents/documents-screen";

export default function Page({
  params,
}: {
  params: Promise<{ pillar: string; caseId: string; documentId: string }>;
}) {
  return <ReviewScreen params={params} section="document-intake" />;
}
