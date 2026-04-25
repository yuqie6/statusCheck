import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import AdminApp from './AdminApp'
import { applyThemePreference, readThemePreference } from './lib/theme'
import './styles.css'

applyThemePreference(readThemePreference())

const path = window.location.pathname.replace(/\/+$/, '')
const RootApp = path === '/admin' ? AdminApp : App

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>,
)
