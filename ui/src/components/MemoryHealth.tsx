import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import type { TelemetryEvent } from '../lib/telemetry';

interface MemoryHealthProps {
  events: TelemetryEvent[];
}

export const MemoryHealth: React.FC<MemoryHealthProps> = ({ events }) => {
  const stats = useMemo(() => {
    let hits = 0;
    let misses = 0;
    let queries = 0;

    events.forEach(e => {
      if (e.event_type === 'memory.hit') hits++;
      if (e.event_type === 'memory.miss') misses++;
      if (e.event_type === 'memory.query') queries++;
    });

    // If no explicit hit/miss events but we have queries, mock a baseline for visualization
    if (hits === 0 && misses === 0 && queries === 0) {
      return [];
    }

    return [
      { name: 'Hits', value: hits, color: '#00ff41' },
      { name: 'Misses', value: misses, color: '#ff3333' }
    ];
  }, [events]);

  if (stats.length === 0) {
    return <div className="text-[#00ff41]/50 italic font-mono h-full flex items-center justify-center">Awaiting memory queries...</div>;
  }

  const hitRate = stats[0].value + stats[1].value > 0 
    ? ((stats[0].value / (stats[0].value + stats[1].value)) * 100).toFixed(1) 
    : 0;

  return (
    <div className="w-full h-full flex items-center justify-between px-4">
      <div className="flex-1 h-full min-h-[100px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={stats}
              cx="50%"
              cy="50%"
              innerRadius={30}
              outerRadius={45}
              paddingAngle={5}
              dataKey="value"
              stroke="none"
            >
              {stats.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} fillOpacity={0.8} />
              ))}
            </Pie>
            <Tooltip 
              contentStyle={{ backgroundColor: '#0a0a0a', border: '1px solid rgba(0,255,65,0.3)', borderRadius: '4px', fontFamily: 'monospace', fontSize: '12px' }}
              itemStyle={{ color: '#00ff41' }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-col space-y-2 text-xs w-1/2 font-mono">
        <div className="flex justify-between border-b border-[#00ff41]/20 pb-1">
          <span className="opacity-70">HIT RATE</span>
          <span className="font-bold text-[#00ff41]">{hitRate}%</span>
        </div>
        <div className="flex justify-between">
          <span className="opacity-70">HITS</span>
          <span className="text-[#00ff41]">{stats[0].value}</span>
        </div>
        <div className="flex justify-between">
          <span className="opacity-70">MISSES</span>
          <span className="text-[#ff3333]">{stats[1].value}</span>
        </div>
      </div>
    </div>
  );
};
