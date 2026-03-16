import React, { useMemo } from 'react';
import type { TelemetryEvent } from '../lib/telemetry';

interface HeartbeatGridProps {
  events: TelemetryEvent[];
}

export const HeartbeatGrid: React.FC<HeartbeatGridProps> = ({ events }) => {
  // Generate a 48-slot grid representing recent heartbeat tasks
  const grid = useMemo(() => {
    const slots = Array(48).fill({ status: 'pending', id: null });
    
    // Filter heartbeat events
    const hbEvents = events
      .filter(e => e.event_type.startsWith('heartbeat.'))
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 48); // We only care about the last 48 events for the grid

    hbEvents.forEach((ev, idx) => {
      let status = 'pending';
      if (ev.event_type === 'heartbeat.complete') status = 'success';
      if (ev.event_type === 'heartbeat.miss' || ev.event_type === 'heartbeat.error') status = 'error';
      if (ev.event_type === 'heartbeat.start') status = 'active';

      slots[idx] = { status, id: ev.event_id, ...ev };
    });

    return slots.reverse(); // oldest to newest left to right
  }, [events]);

  return (
    <div className="w-full h-full flex flex-col justify-center">
      <div className="grid grid-cols-12 gap-1 gap-y-2 p-2">
        {grid.map((slot, i) => {
          let bgClass = "bg-[#00ff41]/5 border-[#00ff41]/20"; // pending
          if (slot.status === 'success') bgClass = "bg-[#00ff41]/80 border-[#00ff41] shadow-[0_0_5px_rgba(0,255,65,0.5)]";
          if (slot.status === 'error') bgClass = "bg-red-500/80 border-red-500 shadow-[0_0_5px_rgba(239,68,68,0.5)]";
          if (slot.status === 'active') bgClass = "bg-yellow-400/80 border-yellow-400 animate-pulse";

          return (
            <div 
              key={slot.id || i} 
              className={`w-full aspect-square rounded-[2px] border ${bgClass} transition-colors group relative`}
            >
              {slot.id && (
                <div className="opacity-0 group-hover:opacity-100 absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-50 bg-[#0a0a0a] border border-[#00ff41]/50 p-1.5 rounded shadow-lg pointer-events-none whitespace-nowrap text-[10px]">
                  <div className="text-[#00ff41] font-bold">{slot.event_type}</div>
                  <div className="text-[#00ff41]/70">{slot.component}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
