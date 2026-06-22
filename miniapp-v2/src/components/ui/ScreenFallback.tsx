import { CardSkeleton, Skeleton } from './Skeleton';

/** Generic skeleton shown while a lazy screen chunk loads. */
export function ScreenFallback() {
  return (
    <div class="screen space-y-4" aria-busy="true" aria-label="Loading">
      <Skeleton w="55%" h="1.6rem" />
      <CardSkeleton />
      <CardSkeleton />
    </div>
  );
}
