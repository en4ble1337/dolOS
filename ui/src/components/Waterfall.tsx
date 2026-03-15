import React, { useMemo } from 'react';
import type { TelemetryEvent } from '../lib/telemetry';

interface WaterfallProps {
  events: TelemetryEvent[];
}

export const Waterfall: React.FC<WaterfallProps> = ({ events }) => {
  const traces = useMemo(() => {
    // Group events by trace_id
    const grouped = new Map<string, TelemetryEvent[]>();
    events.forEach(e => {
      if (e.trace_id && e.trace_id !== 'default') {
        if (!grouped.has(e.trace_id)) grouped.set(e.trace_id, []);
        grouped.get(e.trace_id)!.push(e);
      }
    });

    return Array.from(grouped.entries())
      .map(([traceId, traceEvents]) => {
        // Sort events chronologically (oldest first)
        const sorted = [...traceEvents].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
        const startTime = new Date(sorted[0].timestamp).getTime();
        const endTime = new Date(sorted[sorted.length - 1].timestamp).getTime();
        const duration = Math.max(endTime - startTime, sorted[sorted.length - 1].duration_ms || 1);
        
        return {
          id: traceId,
          events: sorted,
          startTime,
          duration,
        };
      })
      .sort((a, b) => b.startTime - a.startTime) // Newest traces first
      .slice(0, 5); // Show last 5 traces to keep UI clean
  }, [events]);

  if (traces.length === 0) {
    return <div className="text-[#00ff41]/50 italic font-mono h-full flex items-center justify-center">Awaiting trace data...</div>;
  }

  return (
    <div className="w-full h-full overflow-y-auto space-y-4 font-mono pr-2 custom-scrollbar">
      {traces.map((trace) => (
        <div key={trace.id} className="border border-[#00ff41]/20 rounded p-3 bg-black/40 text-xs shadow-inner">
          <div className="flex justify-between items-center mb-3 border-b border-[#00ff41]/20 pb-2">
            <span className="font-bold text-[#00ff41] truncate max-w-[200px]" title={trace.id}>
              Trace: {trace.id.substring(0, 8)}...
            </span>
            <span className="text-[#00ff41]/70 bg-[#00ff41]/10 px-2 py-0.5 rounded">{trace.duration.toFixed(0)}ms total</span>
          </div>
          <div className="space-y-2">
            {trace.events.map((ev, i) => {
              // Calculate relative offset and width based on time
              const evStart = new Date(ev.timestamp).getTime();
              // Prevent division by 0
              const safeTraceDuration = trace.duration > 0 ? trace.duration : 1;
              const leftPercent = Math.max(0, Math.min(100, ((evStart - trace.startTime) / safeTraceDuration) * 100));
              
              // Ensure visually distinct widths
              const evDuration = ev.duration_ms || (safeTraceDuration * 0.05); 
              let widthPercent = Math.max(2, Math.min(100 - leftPercent, (evDuration / safeTraceDuration) * 100));
              
              // Colors based on event component or type
              let colorClass = "bg-[#00ff41]/40 border-[#00ff41]/80 text-[#00ff41]";
              if (ev.event_type.includes('error')) colorClass = "bg-red-500/40 border-red-500/80 text-red-400";
              else if (ev.event_type.includes('llm') || ev.component.includes('llm')) colorClass = "bg-yellow-400/40 border-yellow-400/80 text-yellow-300";
              else if (ev.event_type.includes('memory') || ev.component.includes('memory')) colorClass = "bg-blue-400/40 border-blue-400/80 text-blue-300";

              return (
                <div key={ev.event_id || i} className="relative h-7 group w-full">
                   {/* Track Background */}
                   <div className="absolute inset-y-0 left-0 right-0 bg-[#00ff41]/5 rounded border border-[#00ff41]/10" />
                   
                   {/* Waterfall Bar */}
                   <div 
                     className={`absolute top-[2px] bottom-[2px] rounded border-l-2 text-[10px] whitespace-nowrap overflow-hidden px-1 flex items-center shadow-[0_0_5px_rgba(0,0,0,0.5)] transition-all ${colorClass}`}
                     style={{ left: `${leftPercent}%`, width: `${widthPercent}%`, minWidth: '40px' }}
                   >
                     {ev.component}
                   </div>
                   
                   {/* Hover Tooltip - Absolute positioned next to the bar or fallback */}
                   <div className="opacity-0 group-hover:opacity-100 absolute left-0 top-full mt-1 z-50 bg-[#0a0a0a] border border-[#00ff41]/50 p-2 rounded shadow-lg pointer-events-none whitespace-nowrap transition-opacity text-[#00ff41] text-xs">
                     <div className="font-bold border-b border-[#00ff41]/30 pb-1 mb-1">{ev.event_type}</div>
                     <div className="text-[#00ff41]/70">Duration: {ev.duration_ms?.toFixed(2) || 0}ms</div>
                     <div className="text-[#00ff41]/50">Start: {leftPercent.toFixed(1)}% offset</div>
                   </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
};
