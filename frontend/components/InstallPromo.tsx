"use client";

import { useInstall } from "@/lib/install";
import { ChevronIcon, InstallIcon, ShareIcon } from "./icons";

/** "Install FloodWatch", where the browser can; on an iPhone, how to. Nothing
 * once it's installed, or where it can't be. */
export default function InstallPromo() {
  const install = useInstall();
  if (install.kind === "none") return null;
  if (install.kind === "prompt") {
    return (
      <button type="button" className="promo" onClick={() => void install.install()}>
        <span className="promo-icon quiet">
          <InstallIcon />
        </span>
        <span>
          <strong>Install FloodWatch</strong>
          <small>On your home screen, opens full screen. Free, no app store.</small>
        </span>
        <ChevronIcon />
      </button>
    );
  }
  return (
    <div className="promo">
      <span className="promo-icon quiet">
        <ShareIcon />
      </span>
      <span>
        <strong>Add FloodWatch to your Home Screen</strong>
        <small>In Safari, tap Share, then “Add to Home Screen”. iPhone alerts need it.</small>
      </span>
    </div>
  );
}
