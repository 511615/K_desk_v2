import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import WorkbenchPage from './pages/WorkbenchPage.vue'
import CopyPoolPage from './pages/CopyPoolPage.vue'
import './styles.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: WorkbenchPage },
    { path: '/copy-pool', component: CopyPoolPage },
    {
      path: '/account/:login',
      component: WorkbenchPage,
      beforeEnter(to) {
        window.location.assign(to.fullPath)
        return false
      },
    },
  ],
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
})

createApp(App).use(router).use(VueQueryPlugin, { queryClient }).mount('#app')
