"use client";

import { useEffect, useRef, useState } from "react";

const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const MAX_SECONDS = 120;
// Once speech has been heard, this much quiet ends the note by itself --
// people expect a voice box to notice they have stopped talking.
const SILENCE_MS = 2200;
const SPEECH_LEVEL = 0.06;
// Below this the browser handed us (near) nothing: a muted or blocked mic.
const MIN_BYTES = 1200;

export type Recording = { blob: Blob; filename: string };

type WebkitWindow = Window & { webkitAudioContext?: typeof AudioContext };

/**
 * MediaRecorder with the container the browser actually supports (iOS Safari
 * records mp4, Chrome/Android webm), a live input level so the person can see
 * they are being heard, auto-stop after a pause, and a hard two-minute cap.
 */
export function useRecorder(onDone: (rec: Recording) => void) {
  const [state, setState] = useState<"idle" | "recording">("idle");
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef<number | null>(null);
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
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = null;
    audioCtx.current?.close().catch(() => {});
    audioCtx.current = null;
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
    recorder.current = null;
  }

  useEffect(() => cleanup, []);

  function stop() {
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
  }

  function watchLevel(stream: MediaStream) {
    const Ctx = window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    audioCtx.current = ctx;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    let spoke = false;
    let quietSince = performance.now();
    const started = performance.now();

    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      const rms = Math.sqrt(sum / buf.length);
      const now = performance.now();
      setLevel(Math.min(1, rms * 6));
      if (rms > SPEECH_LEVEL) {
        quietSince = now;
        if (!spoke) {
          spoke = true;
          setHeard(true);
        }
      } else if (spoke && now - quietSince > SILENCE_MS && now - started > 1500) {
        stop();
        return;
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }

  async function start() {
    setError(null);
    setHeard(false);
    setLevel(0);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError("Microphone access was blocked. Allow it in the browser settings and try again.");
      return;
    }
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      const type = rec.mimeType || mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      cleanup();
      setState("idle");
      setLevel(0);
      const blob = new Blob(chunks, { type });
      if (blob.size < MIN_BYTES) {
        setError("Nothing was recorded. Check the microphone isn't muted and try again.");
        return;
      }
      done.current({ blob, filename: `note.${ext}` });
    };
    recorder.current = rec;
    // A timeslice makes Safari hand over data as it records rather than only
    // on stop, which it sometimes skips for a very short note.
    rec.start(1000);
    setSeconds(0);
    setState("recording");
    watchLevel(stream);
    timer.current = setInterval(() => {
      setSeconds((s) => s + 1);
    }, 1000);
  }

  useEffect(() => {
    if (state === "recording" && seconds >= MAX_SECONDS) stop();
  }, [state, seconds]);

  return { supported, state, seconds, level, heard, error, start, stop };
}
