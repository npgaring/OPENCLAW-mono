import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConsolePage } from './pages/ConsolePage';
import { ProjectsPage } from './pages/ProjectsPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ConsolePage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
