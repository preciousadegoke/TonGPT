import { Component, type ComponentChildren } from 'preact';

interface Props {
  children: ComponentChildren;
}
interface State {
  error: Error | null;
}

/** App-level safety net — keeps a render crash from white-screening the app. */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    // eslint-disable-next-line no-console
    console.error('[TonGPT] render error:', error);
  }

  render() {
    if (this.state.error) {
      return (
        <div class="flex flex-col items-center justify-center h-full gap-4 px-8 text-center animate-fade-in">
          <div class="text-5xl">⚠️</div>
          <h2 class="text-lg font-bold">Something went wrong</h2>
          <p class="text-hint text-sm">{this.state.error.message}</p>
          <button class="btn-primary" onClick={() => location.reload()}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
