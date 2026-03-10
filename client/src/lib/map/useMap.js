import { useEffect, useRef, useState } from 'react';
import { getProvider } from './index';

export function useMap(containerRef, { center, zoom }) {
  const provider = getProvider();
  const initRef = useRef(false);
  const [map, setMap] = useState(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (initRef.current) return;
    initRef.current = true;

    provider
      .loadSDK()
      .then(() => {
        if (!containerRef.current) return;
        const instance = provider.createMap(containerRef.current, center, zoom);
        setMap(instance);
        setIsReady(true);
      })
      .catch((err) => {
        setError(err.message);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;
    provider.setCenter(map, center);
    provider.setZoom(map, zoom);
  }, [map, center.lat, center.lng, zoom, provider]);

  return { map, isReady, error };
}
