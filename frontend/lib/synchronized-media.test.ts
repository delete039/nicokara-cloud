import { describe, expect, it } from "vitest";

import { synchronizeMediaPair } from "./synchronized-media";

class FakeMedia extends EventTarget {
  currentTime = 0;
  duration = 120;
  paused = true;
  playCalls = 0;
  pauseCalls = 0;

  async play() {
    this.playCalls += 1;
    this.paused = false;
  }

  pause() {
    this.pauseCalls += 1;
    this.paused = true;
  }
}

describe("synchronizeMediaPair", () => {
  it("keeps cloud result and local preview on the same playback time", async () => {
    const cloud = new FakeMedia();
    const preview = new FakeMedia();
    const dispose = synchronizeMediaPair(cloud, preview);

    cloud.currentTime = 53.33;
    cloud.dispatchEvent(new Event("seeking"));
    expect(preview.currentTime).toBe(53.33);

    cloud.dispatchEvent(new Event("play"));
    await Promise.resolve();
    expect(preview.playCalls).toBe(1);

    preview.currentTime = 76.61;
    preview.dispatchEvent(new Event("timeupdate"));
    expect(cloud.currentTime).toBe(76.61);

    preview.dispatchEvent(new Event("pause"));
    expect(cloud.pauseCalls).toBe(1);

    dispose();
    cloud.currentTime = 20;
    cloud.dispatchEvent(new Event("seeking"));
    expect(preview.currentTime).toBe(76.61);
  });

  it("clamps synchronization to the target duration", () => {
    const cloud = new FakeMedia();
    const preview = new FakeMedia();
    preview.duration = 60;
    synchronizeMediaPair(cloud, preview);

    cloud.currentTime = 90;
    cloud.dispatchEvent(new Event("timeupdate"));

    expect(preview.currentTime).toBe(60);
  });
});
