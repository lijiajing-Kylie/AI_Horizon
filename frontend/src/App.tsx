import { HashRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import DailyListPage from './pages/DailyListPage'
import DailyDetailPage from './pages/DailyDetailPage'
import ItemDetailPage from './pages/ItemDetailPage'
import TopicsPage from './pages/TopicsPage'
import TopicDetailPage from './pages/TopicDetailPage'
import SearchPage from './pages/SearchPage'
import FavoritesPage from './pages/FavoritesPage'
import PreferencesPage from './pages/PreferencesPage'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/daily" element={<DailyListPage />} />
          <Route path="/daily/:date" element={<DailyDetailPage />} />
          <Route path="/items/:id" element={<ItemDetailPage />} />
          <Route path="/topics" element={<TopicsPage />} />
          <Route path="/topics/:slug" element={<TopicDetailPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/preferences" element={<PreferencesPage />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
