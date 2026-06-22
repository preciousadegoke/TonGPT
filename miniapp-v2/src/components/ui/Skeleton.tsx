interface SkeletonProps {
  class?: string;
  w?: string;
  h?: string;
  rounded?: string;
}

export function Skeleton({ class: cls = '', w, h = '1rem', rounded = '12px' }: SkeletonProps) {
  return (
    <div
      class={`skeleton ${cls}`}
      style={{ width: w ?? '100%', height: h, borderRadius: rounded }}
      aria-hidden="true"
    />
  );
}

export function CardSkeleton() {
  return (
    <div class="card p-4 space-y-3">
      <Skeleton w="40%" h="0.9rem" />
      <Skeleton w="70%" h="1.4rem" />
      <Skeleton w="100%" h="3rem" />
    </div>
  );
}
