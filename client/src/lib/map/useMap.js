import { useEffect, useMemo, useRef, useState } from 'react';
import { getProvider } from './index';

export function useMap(containerRef, { center, zoom }) {
  const { lat, lng } = center;
  const provider = useMemo(() => getProvider(), []);
  const initRef = useRef(false);
  const initialViewRef = useRef({ center, zoom });
  const [map, setMap] = useState(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (initRef.current) return;
    initRef.current = true;
    let cancelled = false;

    provider
      .loadSDK()
      .then(() => {
        if (cancelled || !containerRef.current) return;
        const instance = provider.createMap(containerRef.current, initialViewRef.current.center, initialViewRef.current.zoom);
        setMap(instance);
        setIsReady(true);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '지도 SDK를 불러오지 못했습니다.');
      });

    return () => {
      cancelled = true;
      // React StrictMode re-runs effects in development. Allow the next
      // invocation to initialize the SDK/map again after this one is cleaned up.
      initRef.current = false;
    };
  }, [containerRef, provider]);

  useEffect(() => {
    if (!map) return;
    provider.setCenter(map, { lat, lng });
    provider.setZoom(map, zoom);
  }, [map, lat, lng, zoom, provider]);

  return { map, isReady, error };
}
