import { ref, onMounted, onUnmounted, type Ref } from "vue"

export function useAutoScroll(containerRef: Ref<HTMLElement | null>) {
  const isAtBottom = ref(true)

  function scrollToBottom(smooth = true) {
    const element = containerRef.value
    if (!element) return
    element.scrollTo({
      top: element.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    })
  }

  function onScroll() {
    const element = containerRef.value
    if (!element) return
    const threshold = 100
    isAtBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < threshold
  }

  onMounted(() => {
    containerRef.value?.addEventListener("scroll", onScroll)
  })

  onUnmounted(() => {
    containerRef.value?.removeEventListener("scroll", onScroll)
  })

  return { isAtBottom, scrollToBottom }
}
