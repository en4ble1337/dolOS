import React, { useMemo } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { TelemetryEvent } from '../lib/telemetry';

interface TokenChartProps {
  events: TelemetryEvent[];
}

export const TokenChart: React.FC<TokenChartProps> = ({ events }) => {
  const data = useMemo(() => {
    // Filter to llm.call.end events and map to a simplified format
    return events
      .filter((e) => e.event_type.toUpperCase() === 'LLM.CALL.END' || e.event_type === 'llm.call.end')
      .reverse() // from oldest to newest since the feed is newest first
      .map((e) => {
        const timeStr = new Date(e.timestamp).toISOString().split('T')[1].split('.')[0];
        return {
          time: timeStr,
          tokens: e.payload?.total_tokens || 0,
        };
      })
      .slice(-20); // Show last 20
  }, [events]);

  if (data.length === 0) {
    return <div className="text-[#00ff41]/50 italic font-mono h-full flex items-center justify-center">Awaiting LLM token data...</div>;
  }

  return (
    <div className="w-full h-full min-h-[150px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="colorTokens" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#00ff41" stopOpacity={0.8} />
              <stop offset="95%" stopColor="#00ff41" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#00ff41" strokeOpacity={0.2} vertical={false} />
          <XAxis dataKey="time" stroke="#00ff41" strokeOpacity={0.5} fontSize={10} tickLine={false} />
          <YAxis stroke="#00ff41" strokeOpacity={0.5} fontSize={10} tickLine={false} axisLine={false} />
          <Tooltip 
            contentStyle={{ backgroundColor: '#0a0a0a', border: '1px solid rgba(0,255,65,0.3)', borderRadius: '4px', fontFamily: 'monospace' }}
            itemStyle={{ color: '#00ff41' }}
          />
          <Area type="monotone" dataKey="tokens" stroke="#00ff41" fillOpacity={1} fill="url(#colorTokens)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};
