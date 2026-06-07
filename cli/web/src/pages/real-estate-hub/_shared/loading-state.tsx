import { useLocation } from "react-router-dom";
import { RouteSkeleton } from "@/components/route-skeletons";

export function LoadingState() {
  const location = useLocation();
  return <RouteSkeleton path={location.pathname} />;
}
