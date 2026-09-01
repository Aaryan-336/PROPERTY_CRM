import { SkeletonRow } from "@/components/ui";

/**
 * Shown the instant a navigation starts, in place of the page being fetched.
 *
 * It sits inside the app group's layout, so the header and the dock stay put
 * and only the content region is replaced -- the frame of the app never
 * flickers, which is most of what separates "an app" from "a website loading".
 *
 * Worth being clear about what this does and does not do: it makes nothing
 * faster. It removes the interval where a tap has been registered and the
 * screen has not admitted it, which on a sleeping free-tier API can run to
 * several seconds. That interval is where an app feels broken, and it is the
 * cheapest one to fix.
 */
export default function Loading() {
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <span className="skeleton block h-7 w-40 rounded-lg" aria-hidden />
        <span className="skeleton block h-3.5 w-56" aria-hidden />
      </div>

      <div className="space-y-3">
        {/* Five: enough to read as a list, few enough that the placeholder is
            never taller than the content it stands in for. */}
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonRow key={i} />
        ))}
      </div>

      <span className="sr-only" role="status">
        Loading
      </span>
    </div>
  );
}
