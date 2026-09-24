"use client";

import { useEffect, useRef, useState } from "react";

const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const MAX_SECONDS = 120;

export type Recording = { blob: Blob; filename: string };

/** MediaRecorder with the container the browser actually supports (iOS
 *  Safari records mp4, Chrome/Android webm) and a hard two-minute stop. */
export function useRecorder(onDone: (rec: Recording) => void) {
  const [state, setState] = useState<"idle" | "recording">("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  }, [onDone]);

  const supported =
    typeof window !== "undefined" &&
    typeof window.MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia;

  function cleanup() {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
    recorder.current = null;
  }

  useEffect(() => cleanup, []);

  async function start() {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked. Allow it in the browser settings and try again.");
      return;
    }
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      const type = rec.mimeType || mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      cleanup();
      setState("idle");
      done.current({ blob: new Blob(chunks, { type }), filename: `note.${ext}` });
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    timer.current = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) recorder.current?.stop();
        return s + 1;
      });
    }, 1000);
  }

  function stop() {
    recorder.current?.stop();
  }

  return { supported, state, seconds, error, start, stop };
}
