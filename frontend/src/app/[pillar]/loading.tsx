import { CardsSkeleton } from "@/components/shared/skeletons";
import { Skeleton } from "@/components/ui/skeleton";

/** Shown while a page's data is being fetched on the server, so moving between screens never shows a blank area. */
export default function PillarLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <CardsSkeleton count={3} label="Loading the page" />
    </div>
  );
}
