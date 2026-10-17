import { useEffect, useState } from "react";
import { getHealth, readTokenFromLaunchUrl, type HealthReply } from "./api_client/client";
import { messages } from "./messages";

const accessToken = readTokenFromLaunchUrl();
const WARM_UP_POLL_MILLISECONDS = 1000;

function warmUpText(warmUp: HealthReply["warm_up"]): string {
  switch (warmUp.state) {
    case "ready":
      return warmUp.device_name ? messages.gpuReadyWithDevice(warmUp.device_name) : messages.gpuReady;
    case "cpu":
      return messages.noCudaGpuFound;
    case "failed":
      return warmUp.problem ?? messages.gpuNotAvailable;
    default:
      return messages.gpuPreparing;
  }
}

export function App() {
  const [health, setHealth] = useState<HealthReply | null>(null);
  const [engineReachable, setEngineReachable] = useState(true);

  useEffect(() => {
    let timer: number | undefined;
    let leftPage = false;     // a reply that arrives after the cleanup must start no new round
    const askForHealth = async () => {
      try {
        const reply = await getHealth(accessToken);
        if (leftPage) return;
        setHealth(reply);
        if (reply.warm_up.state === "not_started" || reply.warm_up.state === "running") timer = window.setTimeout(askForHealth, WARM_UP_POLL_MILLISECONDS);
      } catch {
        setEngineReachable(false);
      }
    };
    askForHealth();
    return () => {
      leftPage = true;
      window.clearTimeout(timer);
    };
  }, []);

  if (!engineReachable) return <p>{messages.engineStopped}</p>;
  return (
    <main>
      <h1>UrbanSolarCarver {health?.version}</h1>
      <p>{health ? warmUpText(health.warm_up) : ""}</p>
    </main>
  );
}
