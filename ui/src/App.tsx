import { useTelemetry } from './lib/telemetry';
import { Activity, Webhook, Box, Zap, RefreshCw, Cpu, HeartPulse } from 'lucide-react';
import { TokenChart } from './components/TokenChart';
import { Waterfall } from './components/Waterfall';
import { MemoryHealth } from './components/MemoryHealth';
import { HeartbeatGrid } from './components/HeartbeatGrid';

function App() {
  const { events, isConnected, clearEvents } = useTelemetry();

  return (
    <div className="min-h-screen bg-matrix-dark text-matrix-green p-4 font-mono">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-matrix-green/30 pb-4 mb-6">
        <div className="flex items-center space-x-3">
          <Cpu className="w-8 h-8" />
          <h1 className="text-2xl font-bold tracking-widest text-[#00ff41]">
            OPENCLAW :: SYSTEM_OBSERVABILITY
          </h1>
        </div>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-sm uppercase">{isConnected ? 'Uplink Established' : 'No Connection'}</span>
          </div>
          <button 
            onClick={clearEvents}
            className="p-2 border border-matrix-green/30 hover:bg-matrix-green/10 rounded transition-colors"
            title="Clear Feed"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Live Feed */}
        <section className="lg:col-span-1 border border-matrix-green/30 rounded-lg bg-matrix-panel/50 overflow-hidden flex flex-col h-[80vh]">
          <div className="p-3 border-b border-matrix-green/30 bg-matrix-dark flex items-center gap-2">
            <Activity className="w-4 h-4" />
            <h2 className="uppercase font-bold text-sm tracking-wider">Live System Feed</h2>
            <span className="ml-auto text-xs opacity-50 flex items-center bg-black px-2 py-0.5 rounded">{events.length} events</span>
          </div>
          <div className="p-4 overflow-y-auto flex-1 space-y-3 font-mono text-sm shadow-inner bg-[#0a0a0a] custom-scrollbar">
            {events.length === 0 ? (
              <div className="h-full flex items-center justify-center opacity-50 italic">
                Awaiting telemetry...
              </div>
            ) : (
              events.map(ev => (
                <div key={ev.event_id} className="border-l-2 border-matrix-green/50 pl-3 py-1 bg-matrix-green/5 hover:bg-matrix-green/10 transition-colors">
                  <div className="flex justify-between text-xs opacity-70 mb-1">
                    <span>[{new Date(ev.timestamp).toISOString().split('T')[1].split('.')[0]}]</span>
                    <span className="uppercase">{ev.component}</span>
                  </div>
                  <div className="font-bold text-green-300">{ev.event_type}</div>
                  {ev.duration_ms && (
                    <div className="text-xs text-yellow-500 mt-1">
                      Duration: {ev.duration_ms.toFixed(2)}ms
                    </div>
                  )}
                  {ev.payload !== undefined && ev.payload !== null && (
                    <pre className="mt-2 text-xs opacity-80 overflow-x-auto p-2 bg-black/40 rounded">
                      {JSON.stringify(ev.payload, null, 2)}
                    </pre>
                  )}
                </div>
              ))
            )}
          </div>
        </section>

        {/* Right Column - Traces & Metrics */}
        <section className="lg:col-span-2 space-y-6 flex flex-col h-[80vh]">
          {/* Traces Block */}
          <div className="flex-1 border border-matrix-green/30 rounded-lg bg-[#0a0a0a] overflow-hidden flex flex-col relative">
            {/* Ambient matrix glow */}
            <div className="absolute inset-0 bg-matrix-green/5 mix-blend-overlay pointer-events-none" />
            <div className="p-3 border-b border-matrix-green/30 bg-matrix-dark flex items-center gap-2 relative z-10">
              <Webhook className="w-4 h-4" />
              <h2 className="uppercase font-bold text-sm tracking-wider">Active Traces</h2>
            </div>
            <div className="p-4 flex-1 flex flex-col items-center justify-center text-sm relative z-10 overflow-hidden">
              <Waterfall events={events} />
            </div>
          </div>
          
          {/* Metrics Block */}
          <div className="h-[40%] grid grid-cols-3 gap-6">
            <div className="border border-matrix-green/30 rounded-lg bg-[#0a0a0a] p-4 relative overflow-hidden">
               <div className="absolute top-0 right-0 w-32 h-32 bg-matrix-green/5 blur-3xl" />
               <div className="flex items-center gap-2 mb-4 opacity-80 relative z-10">
                 <Zap className="w-4 h-4 text-yellow-400" />
                 <h3 className="uppercase text-xs font-bold">LLM Token Velocity</h3>
               </div>
               <div className="h-[calc(100%-32px)] flex flex-col items-center justify-center text-sm relative z-10 p-2">
                 <TokenChart events={events} />
               </div>
            </div>
            <div className="border border-matrix-green/30 rounded-lg bg-[#0a0a0a] p-4 relative overflow-hidden">
               <div className="flex items-center gap-2 mb-4 opacity-80 relative z-10">
                 <Box className="w-4 h-4 text-blue-400" />
                 <h3 className="uppercase text-xs font-bold">Memory Health</h3>
               </div>
               <div className="h-[calc(100%-32px)] flex flex-col items-center justify-center text-sm relative z-10">
                 <MemoryHealth events={events} />
               </div>
            </div>
            <div className="border border-matrix-green/30 rounded-lg bg-[#0a0a0a] p-4 relative overflow-hidden">
               <div className="flex items-center gap-2 mb-4 opacity-80 relative z-10">
                 <HeartPulse className="w-4 h-4 text-red-400" />
                 <h3 className="uppercase text-xs font-bold">Heartbeat Status</h3>
               </div>
               <div className="h-[calc(100%-32px)] flex flex-col items-center justify-center text-sm relative z-10">
                 <HeartbeatGrid events={events} />
               </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
