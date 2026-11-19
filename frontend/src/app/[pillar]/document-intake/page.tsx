import { DocumentsScreen } from "@/components/documents/documents-screen";

export default function Page({ params }: { params: Promise<{ pillar: string }> }) {
  return <DocumentsScreen params={params} section="document-intake" />;
}
