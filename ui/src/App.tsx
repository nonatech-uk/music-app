import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Shell from './components/layout/Shell.tsx'
import Tracks from './pages/Tracks.tsx'
import TrackDetail from './pages/TrackDetail.tsx'
import Artists from './pages/Artists.tsx'
import ArtistDetail from './pages/ArtistDetail.tsx'
import Review from './pages/Review.tsx'

export default function App() {
  return (
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/tracks" replace />} />
          <Route path="/tracks" element={<Tracks />} />
          <Route path="/tracks/:id" element={<TrackDetail />} />
          <Route path="/artists" element={<Artists />} />
          <Route path="/artists/:id" element={<ArtistDetail />} />
          <Route path="/review" element={<Review />} />
          <Route path="*" element={<div className="text-text-secondary p-8">Page not found</div>} />
        </Routes>
      </Shell>
    </BrowserRouter>
  )
}
