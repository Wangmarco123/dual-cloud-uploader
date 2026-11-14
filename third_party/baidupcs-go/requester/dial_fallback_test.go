// Local addition, 2026-11-14: regression for fallback after a cached address fails.
package requester

import (
	"context"
	"net"
	"testing"
	"time"
)

func TestDialContextFallsBackAfterUnreachableCachedAddress(t *testing.T) {
	l, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	defer l.Close()
	_, port, _ := net.SplitHostPort(l.Addr().String())
	SetTCPHostBind("localhost", "127.0.0.2")
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	c, e := dialContext(ctx, "tcp", net.JoinHostPort("localhost", port))
	if e != nil {
		t.Fatalf("fallback failed: %v", e)
	}
	c.Close()
}
