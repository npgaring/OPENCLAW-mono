import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConsolePage } from './pages/ConsolePage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ConsolePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
